from data.CCF import CCFDataSet
import torch
from torch.utils.data import DataLoader
from model.models import Generator, Discriminator, FeatureExtractor
from Parser import parser
import sys
import torch
import torch.optim as optim
import torch.optim.lr_scheduler as lr_scheduler
import torch.nn as nn
import torchvision
import torchvision.datasets as datasets
import torchvision.transforms as transforms
from tensorboard_logger import configure, log_value
from data.utils import Visualizer

device = torch.device("cuda:0")

opt = parser.parse_args()
print(opt)

normalize = transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                 std=[0.5, 0.5, 0.5])

scale = transforms.Compose([transforms.ToPILImage(),
                            transforms.Resize(opt.imageSize),
                            transforms.ToTensor(),
                            transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                                 std=[0.5, 0.5, 0.5])
                            ])

data_train = CCFDataSet()
dataloader = DataLoader(data_train, batch_size=opt.batchSize, shuffle=True, num_workers=0)

generator = Generator(16, opt.upSampling)

discriminator = Discriminator()

# For the content loss
feature_extractor = FeatureExtractor(torchvision.models.vgg19(pretrained=True))
print(feature_extractor)
content_criterion = nn.MSELoss()
adversarial_criterion = nn.BCELoss()

ones_const = torch.ones(opt.batchSize, 1)

# if gpu is to be used
generator.to(device)
discriminator.to(device)
feature_extractor.to(device)
content_criterion.to(device)
adversarial_criterion.to(device)
ones_const = ones_const.to(device)

optim_generator = optim.Adam(generator.parameters(), lr=opt.generatorLR)
optim_discriminator = optim.Adam(discriminator.parameters(), lr=opt.discriminatorLR)

visualizer = Visualizer(image_size=opt.imageSize * opt.upSampling)

low_res = torch.FloatTensor(opt.batchSize, 3, opt.imageSize, opt.imageSize)

# Pre-train generator using raw MSE loss
print('Generator pre-training')
# generator.load_state_dict(torch.load('pth/generator_pretrain.pth'))
# for epoch in range(5):
#     mean_generator_content_loss = 0.0
#
#     for i, data in enumerate(dataloader):
#         # Generate data
#         high_res_real = data
#
#         if opt.batchSize != high_res_real.shape[0]:
#             break
#
#         # Downsample images to low resolution
#         for j in range(high_res_real.shape[0]):
#             low_res[j] = scale(high_res_real[j])
#             high_res_real[j] = normalize(high_res_real[j])
#
#         # Generate real and fake inputs
#
#         high_res_real = high_res_real.to(device)
#         high_res_fake = generator(low_res.to(device))
#
#         ######### Train generator #########
#         generator.zero_grad()
#
#         generator_content_loss = content_criterion(high_res_fake, high_res_real)
#         mean_generator_content_loss += generator_content_loss.item()
#
#         generator_content_loss.backward()
#         optim_generator.step()
#
#         ######### Status and display #########
#         sys.stdout.write('\r[%d/%d][%d/%d] Generator_MSE_Loss: %.4f' % (
#             epoch, 10, i, len(dataloader), generator_content_loss.item()))
#         visualizer.show(low_res, high_res_real.cpu().data, high_res_fake.cpu().data)
#
#     sys.stdout.write('\r[%d/%d][%d/%d] Generator_MSE_Loss: %.4f\n' % (
#         epoch, 10, i, len(dataloader), mean_generator_content_loss / len(dataloader)))
#     # log_value('generator_mse_loss', mean_generator_content_loss / len(dataloader), epoch)
#
# # Do checkpointing
# torch.save(generator.state_dict(), '%s/generator_pretrain.pth' % opt.out)

# SRGAN training
optim_generator = optim.Adam(generator.parameters(), lr=opt.generatorLR * 0.1)
optim_discriminator = optim.Adam(discriminator.parameters(), lr=opt.discriminatorLR * 0.1)

generator.load_state_dict(torch.load('pth/generator_final.pth'))
discriminator.load_state_dict(torch.load('pth/discriminator_final.pth'))

print('SRGAN training')
for epoch in range(opt.nEpochs):
    mean_generator_content_loss = 0.0
    mean_generator_adversarial_loss = 0.0
    mean_generator_total_loss = 0.0
    mean_discriminator_loss = 0.0

    for i, data in enumerate(dataloader):
        # Generate data
        high_res_real = data
        if opt.batchSize != high_res_real.shape[0]:
            break

        # Downsample images to low resolution
        for j in range(opt.batchSize):
            low_res[j] = scale(high_res_real[j])
            high_res_real[j] = normalize(high_res_real[j])

        # Generate real and fake inputs

        high_res_real = high_res_real.to(device)
        high_res_fake = generator(low_res.to(device))
        target_real = (torch.rand(opt.batchSize, 1) * 0.5 + 0.7).to(device)
        target_fake = (torch.rand(opt.batchSize, 1) * 0.3).to(device)

        ######### Train discriminator #########
        discriminator.zero_grad()

        discriminator_loss = adversarial_criterion(discriminator(high_res_real), target_real) + \
                             adversarial_criterion(discriminator(high_res_fake.data), target_fake)
        mean_discriminator_loss += discriminator_loss.item()

        discriminator_loss.backward()
        optim_discriminator.step()

        ######### Train generator #########
        generator.zero_grad()

        real_features = feature_extractor(high_res_real).data
        fake_features = feature_extractor(high_res_fake)

        generator_content_loss = content_criterion(high_res_fake, high_res_real) + 0.006 * content_criterion(
            fake_features, real_features)
        mean_generator_content_loss += generator_content_loss.item()
        generator_adversarial_loss = adversarial_criterion(discriminator(high_res_fake), ones_const)
        mean_generator_adversarial_loss += generator_adversarial_loss.item()

        generator_total_loss = generator_content_loss + 1e-3 * generator_adversarial_loss
        mean_generator_total_loss += generator_total_loss.item()

        generator_total_loss.backward()
        optim_generator.step()

        ######### Status and display #########
        sys.stdout.write(
            '\r[%d/%d][%d/%d] Discriminator_Loss: %.4f Generator_Loss (Content/Advers/Total): %.4f/%.4f/%.4f' % (
                epoch, opt.nEpochs, i, len(dataloader),
                discriminator_loss.item(), generator_content_loss.item(), generator_adversarial_loss.item(),
                generator_total_loss.item()))
        visualizer.show(low_res, high_res_real.cpu().data, high_res_fake.cpu().data)

    sys.stdout.write(
        '\r[%d/%d][%d/%d] Discriminator_Loss: %.4f Generator_Loss (Content/Advers/Total): %.4f/%.4f/%.4f\n' % (
            epoch, opt.nEpochs, i, len(dataloader),
            mean_discriminator_loss / len(dataloader), mean_generator_content_loss / len(dataloader),
            mean_generator_adversarial_loss / len(dataloader), mean_generator_total_loss / len(dataloader)))

    # log_value('generator_content_loss', mean_generator_content_loss / len(dataloader), epoch)
    # log_value('generator_adversarial_loss', mean_generator_adversarial_loss / len(dataloader), epoch)
    # log_value('generator_total_loss', mean_generator_total_loss / len(dataloader), epoch)
    # log_value('discriminator_loss', mean_discriminator_loss / len(dataloader), epoch)

    # Do checkpointing
    torch.save(generator.state_dict(), '%s/generator_final.pth' % opt.out)
    torch.save(discriminator.state_dict(), '%s/discriminator_final.pth' % opt.out)
